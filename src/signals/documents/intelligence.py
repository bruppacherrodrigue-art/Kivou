"""Du texte du dossier aux exigences — avec un validateur qui a le dernier mot.

Deux chemins, un seul juge :

    blocs de texte ──▶ extracteur déterministe ─┐
                   └─▶ modèle de langue ────────┴──▶ VALIDATEUR ──▶ exigences

Le validateur n'accorde aucune confiance à qui lui parle. Il vérifie que
l'extrait proposé **existe réellement** dans le texte source, aux espaces près,
et rejette tout le reste. C'est ce qui rend une invention structurellement
impossible : un modèle peut écrire n'importe quoi, il ne peut pas fabriquer un
passage qui se retrouve dans le document.

Le partage des rôles est strict :

- **déterministe** : dates, nombres, unités, localisation du texte, empreintes,
  modalité (obligation / interdiction / option / contexte) ;
- **modèle de langue** : comprendre une phrase difficile et proposer une
  classification — jamais un calcul, jamais un chiffre.

Un document est une **entrée non fiable**. S'il contient « ignore les
instructions précédentes », c'est du contenu documentaire, pas une consigne.
"""

from __future__ import annotations

import collections
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import Field

from signals.documents.archive import expand
from signals.documents.classification import (  # noqa: F401 — ré-exports : surface publique stable
    MAX_SENTENCE_CHARS,
    MIN_SENTENCE_CHARS,
    SEMANTIC_CONTRACT_VERSION,
    UNTRUSTED_PROMPT_HEADER,
    HeuristicClassifier,
    ObligationSubject,
    RequirementClassifier,
    SemanticClassification,
    classify_candidate,
    context_for,
    decide,
)
from signals.documents.extract import TextBlock, extract_text, sniff_media_type
from signals.documents.fetch import content_hash
from signals.documents.language import (
    _BID_PHASE,
    classify_requirement,
    confidence_for,
    detect_modality,
    extract_quantity,
    normalize_for_match,
    obligation_subject,
    sentences,
)
from signals.documents.model import CoverageStatus, TenderDocument
from signals.documents.requirements import (
    Confidence,
    ExecutionRequirement,
    Modality,
    RequirementType,
)
from signals.documents.spans import SpanPiece, logical_spans
from signals.documents.triage import detect_language, document_kind, relevance_rank
from signals.domain import EventRef, Evidence, SourceSystem
from signals.domain.values import CanonicalModel, NonEmptyStr

ENGINE_VERSION = "document-intelligence-v0.1"

EXECUTION_KINDS: tuple[str, ...] = (
    "technical_specification",
    "contract_conditions",
    "bill_of_quantities",
    "annex",
    "unknown",
)


@dataclass(frozen=True)
class RequirementCandidate:
    """Une proposition, d'où qu'elle vienne. Elle n'est pas encore une exigence."""

    requirement_type: RequirementType
    modality: Modality
    statement: str
    source_excerpt: str
    source_locator: str
    confidence: Confidence = "medium"


class RequirementExtractionModel(Protocol):
    """Point d'extension pour un modèle de langue.

    Sa sortie passe par le même validateur que le reste : proposer un extrait
    introuvable dans le texte le fait rejeter, quelle que soit sa confiance.
    """

    name: str
    version: str

    def propose(self, block: TextBlock) -> list[RequirementCandidate]:
        """Propose des exigences pour un bloc de texte donné."""
        ...


class DeterministicExtractor:
    """Lit les formes normatives du texte, sans modèle de langue.

    Elle distingue quatre états — obligation, interdiction, option, contexte — et
    n'émet rien pour le dernier : « le précédent contrat exigeait une astreinte »
    décrit le passé.
    """

    name = "deterministic"
    version = ENGINE_VERSION

    def __init__(self, *, prefilter: bool = True) -> None:
        # `prefilter=True` reproduit SPEC-006 : le tri sémantique est fait ici, par
        # des motifs. Avec un classeur sémantique branché, il vaut mieux le
        # désactiver — le modèle voit alors la phrase et **dit** pourquoi elle est
        # écartée, ce qui alimente les diagnostics au lieu de les masquer.
        self.prefilter = prefilter

    def propose(self, block: TextBlock) -> list[RequirementCandidate]:
        candidates: list[RequirementCandidate] = []
        for sentence in sentences(block.text):
            modality = detect_modality(sentence)
            if modality in (None, "informational"):
                continue
            if self.prefilter:
                if obligation_subject(sentence) == "buyer":
                    continue
                if _BID_PHASE.search(sentence):
                    continue
                # Une amorce de liste (« la prise de force doit : ») n'énonce rien :
                # l'obligation est dans les items qui suivent.
                if sentence.rstrip().endswith((":", "…")):
                    continue
            candidates.append(
                RequirementCandidate(
                    requirement_type=classify_requirement(sentence),
                    modality=modality,
                    statement=re.sub(r"\s+", " ", sentence).strip(),
                    source_excerpt=sentence,
                    source_locator=block.locator,
                    confidence=confidence_for(sentence, modality, block),
                )
            )
        return candidates


# ─── Validation ─────────────────────────────────────────────────────────────────


@dataclass
class ValidationOutcome:
    accepted: list[ExecutionRequirement] = field(default_factory=list)
    rejected: list[tuple[RequirementCandidate, str]] = field(default_factory=list)


def validate_candidates(
    candidates: list[RequirementCandidate],
    *,
    block: TextBlock,
    document: TenderDocument,
    method: str,
) -> ValidationOutcome:
    """Le juge. Une proposition sans passage retrouvable est rejetée, point.

    C'est ici que se joue la garantie de SPEC-006 : l'extrait doit exister dans
    le texte du bloc, aux espaces près. Un modèle qui invente une phrase
    plausible échoue à ce test.
    """
    outcome = ValidationOutcome()
    haystack = normalize_for_match(block.text)

    for candidate in candidates:
        excerpt = (candidate.source_excerpt or "").strip()
        if not excerpt:
            outcome.rejected.append((candidate, "aucun extrait source"))
            continue
        if normalize_for_match(excerpt) not in haystack:
            outcome.rejected.append((candidate, "extrait introuvable dans le texte source"))
            continue
        if candidate.modality == "informational":
            outcome.rejected.append((candidate, "énoncé informatif, pas une exigence"))
            continue

        outcome.accepted.append(
            ExecutionRequirement(
                requirement_type=candidate.requirement_type,
                modality=candidate.modality,
                statement=candidate.statement,
                quantity=extract_quantity(excerpt),
                confidence=candidate.confidence,
                extraction_method="deterministic" if method == "deterministic" else "model",
                engine_version=ENGINE_VERSION,
                evidence=(
                    Evidence(
                        source_system=document.source_system,
                        source_kind="tender_document",
                        source_notice_id=document.source_notice_id,
                        source_procedure_id=document.source_procedure_id,
                        source_url=document.source_url,
                        path=_locator(document, candidate.source_locator),
                        # L'extrait n'est jamais reformulé : la preuve reste la
                        # phrase du document.
                        excerpt=excerpt,
                        retrieved_at=document.retrieved_at,
                    ),
                ),
            )
        )
    return outcome


def _locator(document: TenderDocument, locator: str) -> str:
    name = document.path_in_container or document.name or "document"
    return f"{name} — {locator}"


# ─── Résultat global ────────────────────────────────────────────────────────────


class RejectionTally(CanonicalModel):
    """Combien de candidats ont été écartés, et pourquoi.

    `phase_qualification` est conservé exprès : ces exigences ont une valeur
    probable pour un usage ultérieur, mais elles sont hors périmètre de SPEC-006.
    """

    reason: NonEmptyStr
    count: int = Field(ge=1)


class DocumentIntelligenceResult(CanonicalModel):
    """Ce que le dossier documentaire a livré — y compris quand il n'a rien livré."""

    award_ref: EventRef
    source_system: SourceSystem
    tender_procedure_id: NonEmptyStr | None = None
    documents: tuple[TenderDocument, ...] = ()
    requirements: tuple[ExecutionRequirement, ...] = ()
    coverage_status: CoverageStatus
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[RejectionTally, ...] = ()
    # Renseigné dès qu'un modèle a été appelé : appels, jetons, coût.
    llm_usage: dict[str, Any] | None = None
    classifier: NonEmptyStr | None = None
    contract_version: NonEmptyStr = SEMANTIC_CONTRACT_VERSION
    engine_version: NonEmptyStr = ENGINE_VERSION

    @property
    def readable_documents(self) -> tuple[TenderDocument, ...]:
        return tuple(document for document in self.documents if document.is_readable)


def coverage_for(documents: tuple[TenderDocument, ...], requirements: int) -> CoverageStatus:
    """L'état du dossier — jamais une mesure de confiance sur les exigences."""
    if not documents:
        return "no_documents"
    statuses = {document.access_status for document in documents}
    if any(document.is_readable for document in documents):
        return "documents_analyzed" if requirements else "partial_documents"
    if statuses == {"external"}:
        return "external_only"
    if "auth_required" in statuses:
        return "auth_required"
    if "unsupported" in statuses or "encrypted" in statuses:
        return "unsupported_documents"
    # Une adresse publiée puis morte reste un échec d'accès : le dossier existe,
    # c'est le lien qui a disparu. `no_documents` est réservé au cas où rien n'a
    # jamais été référencé.
    if statuses & {"download_failed", "too_large", "not_found"}:
        return "download_failed"
    return "no_documents"


# ─── Pipeline ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AnalysisLimits:
    """Ce qu'on accepte de lire. Un plafond atteint est dit, jamais subi en silence."""

    max_documents: int = 40
    max_blocks_per_document: int = 5_000
    max_requirements_per_document: int = 500


@dataclass
class DocumentAnalysis:
    """Ce qu'un document a livré — et ce qui a été refusé en chemin."""

    document: TenderDocument
    requirements: list[ExecutionRequirement] = field(default_factory=list)
    rejected: list[tuple[RequirementCandidate, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocks: int = 0
    spans: int = 0
    second_pass_calls: int = 0
    recovered_by_second_pass: int = 0


def requirement_from(
    classification: SemanticClassification,
    *,
    document: TenderDocument,
    locator: str,
    method: str,
    pieces: tuple[SpanPiece, ...] = (),
) -> ExecutionRequirement:
    """Construit l'exigence à partir de la classification ET de l'extrait source.

    L'énoncé est l'extrait **nettoyé des espaces**, jamais une phrase du modèle :
    son rôle est de dire ce que la phrase représente, pas d'en écrire une autre.
    La quantité reste calculée par le code — un modèle ne produit aucun chiffre.

    Quand la phrase était coupée par la mise en page, `pieces` porte un morceau
    par bloc source : l'exigence reçoit alors **autant de preuves que de blocs
    traversés**, chacune citant son propre texte brut et sa propre localisation.
    Jamais une citation unique qui prétendrait venir d'un seul endroit.
    """
    excerpt = classification.source_excerpt.strip()
    if len(pieces) > 1:
        evidence = tuple(
            Evidence(
                source_system=document.source_system,
                source_kind="tender_document",
                source_notice_id=document.source_notice_id,
                source_procedure_id=document.source_procedure_id,
                source_url=document.source_url,
                path=_locator(document, piece.block.locator),
                excerpt=piece.text,
                retrieved_at=document.retrieved_at,
            )
            for piece in pieces
        )
        return ExecutionRequirement(
            requirement_type=classification.requirement_type,
            modality=classification.modality,  # type: ignore[arg-type]
            statement=re.sub(r"\s+", " ", excerpt),
            quantity=extract_quantity(excerpt),
            confidence=classification.confidence,
            extraction_method="deterministic" if method == "deterministic" else "model",
            engine_version=ENGINE_VERSION,
            evidence=evidence,
        )
    return ExecutionRequirement(
        requirement_type=classification.requirement_type,
        modality=classification.modality,  # type: ignore[arg-type]
        statement=re.sub(r"\s+", " ", excerpt),
        quantity=extract_quantity(excerpt),
        confidence=classification.confidence,
        extraction_method="deterministic" if method == "deterministic" else "model",
        engine_version=ENGINE_VERSION,
        evidence=(
            Evidence(
                source_system=document.source_system,
                source_kind="tender_document",
                source_notice_id=document.source_notice_id,
                source_procedure_id=document.source_procedure_id,
                source_url=document.source_url,
                path=_locator(document, locator),
                excerpt=excerpt,
                retrieved_at=document.retrieved_at,
            ),
        ),
    )


def analyze_document(
    document: TenderDocument,
    data: bytes,
    *,
    model: RequirementExtractionModel | None = None,
    classifier: RequirementClassifier | None = None,
    deterministic: bool = True,
    limits: AnalysisLimits | None = None,
) -> DocumentAnalysis:
    """Un document, ses blocs de texte, ses exigences prouvées.

    Le statut d'accès est corrigé par ce qui a été **constaté** : un fichier
    téléchargé mais illisible devient `unsupported`, un PDF protégé `encrypted`.
    Dire « pas d'exigence » là où le format n'a pas pu être ouvert serait faux.
    """
    limits = limits or AnalysisLimits()
    extraction = extract_text(data, name=document.path_in_container or document.name)

    updates: dict[str, object] = {}
    if extraction.media_type and extraction.media_type != document.media_type:
        updates["media_type"] = extraction.media_type
    if not extraction.supported:
        updates["access_status"] = "unsupported"
    elif extraction.encrypted:
        updates["access_status"] = "encrypted"

    blocks = extraction.blocks[: limits.max_blocks_per_document]
    warnings = list(extraction.warnings)
    if len(extraction.blocks) > len(blocks):
        warnings.append(
            f"document tronqué à {len(blocks)} blocs sur {len(extraction.blocks)} : "
            "plafond de lecture atteint"
        )

    language = detect_language(" ".join(block.text for block in blocks[:40]))
    if language and not document.language:
        updates["language"] = language
    if document.kind == "unknown":
        kind = document_kind(
            document.path_in_container or document.name,
            media_type=extraction.media_type or document.media_type,
        )
        if kind != "unknown":
            updates["kind"] = kind

    document = document.model_copy(update=updates) if updates else document
    # Les candidats sont construits sur des unités de texte recollées, pas sur les
    # blocs bruts : c'est ce qui supprime les phrases tronquées par la mise en page.
    spans = logical_spans(blocks)
    analysis = DocumentAnalysis(document=document, warnings=warnings, blocks=len(blocks))
    analysis.spans = len(spans)
    if not extraction.supported or extraction.encrypted:
        return analysis

    # Sans classeur sémantique, on retombe sur les règles de SPEC-006 — dont la
    # précision mesurée est de 52,5 %. Le moteur le signale plutôt que de le taire.
    semantic = classifier is not None
    if classifier is None:
        classifier = HeuristicClassifier()
        analysis.warnings.append(
            "classification heuristique (aucun modèle configuré) : "
            "précision mesurée 52,5 % sur held-out"
        )
    # Le pré-filtrage déterministe n'a de sens que sans modèle : avec lui, mieux
    # vaut que la phrase soit vue et **qualifiée** plutôt que supprimée en silence.
    extractor = DeterministicExtractor(prefilter=not semantic)
    method = "model" if (semantic or model is not None) else "deterministic"

    for index, span in enumerate(spans):
        candidates: list[RequirementCandidate] = []
        if deterministic:
            candidates.extend(extractor.propose(span))  # type: ignore[arg-type]
        if model is not None:
            candidates.extend(model.propose(span))  # type: ignore[arg-type]
        if not candidates:
            continue

        for candidate in candidates:
            attempt = classify_candidate(
                classifier,
                spans,  # type: ignore[arg-type]
                index=index,
                candidate=candidate,
                document_name=document.path_in_container or document.name,
            )
            analysis.second_pass_calls += attempt.escalated
            analysis.recovered_by_second_pass += attempt.recovered
            if not attempt.decision.accepted or attempt.classification is None:
                analysis.rejected.append((candidate, attempt.decision.reason or "rejected"))
                continue
            analysis.requirements.append(
                requirement_from(
                    attempt.classification,
                    document=document,
                    locator=candidate.source_locator,
                    method=method,
                    pieces=span.pieces_for(attempt.classification.source_excerpt.strip()),
                )
            )

        if len(analysis.requirements) >= limits.max_requirements_per_document:
            analysis.warnings.append(
                f"lecture arrêtée à {limits.max_requirements_per_document} exigences : "
                "plafond par document atteint"
            )
            del analysis.requirements[limits.max_requirements_per_document :]
            break

    return analysis


def _requirement_key(requirement: ExecutionRequirement) -> tuple[str, str, str]:
    return (
        requirement.requirement_type,
        requirement.modality,
        normalize_for_match(requirement.statement),
    )


def dedupe_requirements(
    requirements: list[ExecutionRequirement],
) -> list[ExecutionRequirement]:
    """Une exigence répétée reste une exigence — mais ses preuves s'additionnent.

    Le même paragraphe recopié dans deux pièces du dossier ne fait pas deux
    obligations. En revanche, être écrit deux fois est une preuve de plus, pas
    une preuve à jeter.
    """
    merged: dict[tuple[str, str, str], ExecutionRequirement] = {}
    for requirement in requirements:
        key = _requirement_key(requirement)
        existing = merged.get(key)
        if existing is None:
            merged[key] = requirement
            continue
        seen = {(e.path, e.excerpt) for e in existing.evidence}
        additions = tuple(e for e in requirement.evidence if (e.path, e.excerpt) not in seen)
        if not additions:
            continue
        merged[key] = existing.model_copy(update={"evidence": (*existing.evidence, *additions)})
    return list(merged.values())


def _expand_archives(
    items: Sequence[tuple[TenderDocument, bytes | None]],
) -> list[tuple[TenderDocument, bytes | None]]:
    """Une archive n'est pas un document : c'est un contenant.

    Chaque entrée devient un document à part entière, rattaché à l'empreinte de
    son archive. Les entrées refusées par les garde-fous (chemin remontant,
    exécutable, bombe) sont listées mais jamais ouvertes.
    """
    expanded: list[tuple[TenderDocument, bytes | None]] = []
    for document, data in items:
        if data is None or data[:4] != b"PK\x03\x04":
            expanded.append((document, data))
            continue
        if sniff_media_type(document.name, data) != "application/zip":
            expanded.append((document, data))
            continue

        container = document.content_hash or content_hash(data)
        expanded.append((document.model_copy(update={"kind": "archive"}), None))
        for entry in expand(data).accepted:
            if entry.content is None:
                continue
            expanded.append(
                (
                    document.model_copy(
                        update={
                            "name": entry.path.split("/")[-1],
                            "kind": "unknown",
                            "media_type": None,
                            "language": None,
                            "content_hash": content_hash(entry.content),
                            "byte_size": len(entry.content),
                            "container_hash": container,
                            "path_in_container": entry.path,
                        }
                    ),
                    entry.content,
                )
            )
    return expanded


def analyze_dossier(
    *,
    award_ref: EventRef,
    source_system: SourceSystem,
    items: Sequence[tuple[TenderDocument, bytes | None]],
    tender_procedure_id: str | None = None,
    model: RequirementExtractionModel | None = None,
    classifier: RequirementClassifier | None = None,
    deterministic: bool = True,
    limits: AnalysisLimits | None = None,
    warnings: Sequence[str] = (),
) -> DocumentIntelligenceResult:
    """Le dossier d'un award, lu dans l'ordre où il rend le plus, et son état.

    `items` associe chaque document à son contenu — ou à `None` quand il n'a pas
    pu être récupéré. Un document sans contenu reste dans le résultat : c'est
    ainsi qu'un dossier verrouillé se distingue d'un marché sans dossier.
    """
    limits = limits or AnalysisLimits()
    collected = list(warnings)
    expanded = _expand_archives(items)

    readable = [(d, c) for d, c in expanded if c is not None and d.is_readable]
    unreadable = [d for d, c in expanded if c is None or not d.is_readable]
    readable.sort(key=lambda pair: relevance_rank(pair[0]))

    if len(readable) > limits.max_documents:
        collected.append(
            f"dossier tronqué : {limits.max_documents} document(s) lus sur {len(readable)}"
        )
        for document, _ in readable[limits.max_documents :]:
            unreadable.append(document)
        readable = readable[: limits.max_documents]

    documents: list[TenderDocument] = []
    requirements: list[ExecutionRequirement] = []
    rejections: collections.Counter[str] = collections.Counter()
    for document, content in readable:
        analysis = analyze_document(
            document,
            content,
            model=model,
            classifier=classifier,
            deterministic=deterministic,
            limits=limits,
        )
        rejections.update(reason for _, reason in analysis.rejected)
        documents.append(analysis.document)
        if analysis.document.kind in EXECUTION_KINDS:
            requirements.extend(analysis.requirements)
        elif analysis.requirements:
            collected.append(
                f"{analysis.document.name or 'document'} : {len(analysis.requirements)} énoncé(s) "
                f"écarté(s) — pièce de type « {analysis.document.kind} » "
                "(règles de procédure, formulaire ou copie d'annonce), sans portée d'exécution"
            )
        collected.extend(
            f"{analysis.document.name or 'document'} : {warning}" for warning in analysis.warnings
        )

    documents.extend(unreadable)
    deduped = dedupe_requirements(requirements)
    usage = getattr(classifier, "usage", None)
    return DocumentIntelligenceResult(
        award_ref=award_ref,
        source_system=source_system,
        tender_procedure_id=tender_procedure_id,
        documents=tuple(documents),
        requirements=tuple(deduped),
        coverage_status=coverage_for(tuple(documents), len(deduped)),
        warnings=tuple(collected),
        diagnostics=tuple(
            RejectionTally(reason=reason, count=count) for reason, count in rejections.most_common()
        ),
        llm_usage=usage.as_dict() if usage is not None and usage.calls else None,
        classifier=classifier.name if classifier is not None else None,
    )
