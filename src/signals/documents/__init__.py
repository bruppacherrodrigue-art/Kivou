"""Tender Document Intelligence — du dossier de marché aux exigences prouvées.

    ContractAward → procédure → avis d'appel d'offres → documents
                                                          ↓
                                            texte localisé (page, paragraphe, cellule)
                                                          ↓
                                            ExecutionRequirement + Evidence

Trois frontières tenues par construction : le contenu brut n'est jamais mélangé
à son interprétation ; aucune exigence n'existe sans extrait source retrouvable ;
et l'inaccessibilité d'un dossier est un fait mesuré, jamais un « pas de
document ». Les besoins commerciaux appartiennent à SPEC-007.
"""

from signals.documents.archive import (
    ArchiveEntry,
    ArchiveLimits,
    ArchiveReading,
    expand,
    read_archive,
)
from signals.documents.classification import (
    ACCEPTED_MODALITIES,
    CandidateContext,
    Decision,
    HeuristicClassifier,
    LlmUsage,
    RejectionReason,
    RequirementActor,
    RequirementClassifier,
    RequirementPhase,
    SemanticClassification,
    build_classification_prompt,
    context_for,
    decide,
    parse_classification,
)
from signals.documents.discovery import (
    DiscoveryResult,
    DocumentReference,
    LinkageOutcome,
    LinkageStatus,
    auth_required_document,
    linkage_metrics,
    references_from_ted_notice,
    simap_dossier,
)
from signals.documents.extract import (
    ExtractionResult,
    TextBlock,
    extract_text,
    sniff_media_type,
)
from signals.documents.fetch import DocumentFetcher, FetchLimits, FetchResult, content_hash
from signals.documents.intelligence import (
    ENGINE_VERSION,
    UNTRUSTED_PROMPT_HEADER,
    AnalysisLimits,
    DeterministicExtractor,
    DocumentAnalysis,
    DocumentIntelligenceResult,
    RejectionTally,
    RequirementCandidate,
    RequirementExtractionModel,
    analyze_document,
    analyze_dossier,
    classify_requirement,
    coverage_for,
    dedupe_requirements,
    detect_modality,
    extract_quantity,
    requirement_from,
    validate_candidates,
)
from signals.documents.model import (
    AccessFamily,
    CoverageStatus,
    DocumentAccessStatus,
    DocumentKind,
    TenderDocument,
    access_family,
)
from signals.documents.mvp import (
    AUTO_DOCUMENT_REQUIREMENTS_ENABLED,
    DOCUMENT_REQUIREMENT_UNAVAILABLE,
    document_requirement_status,
)
from signals.documents.requirements import (
    ExecutionRequirement,
    Modality,
    RequirementQuantity,
    RequirementType,
)
from signals.documents.triage import detect_language, document_kind, relevance_rank

__all__ = [
    "ACCEPTED_MODALITIES",
    "AUTO_DOCUMENT_REQUIREMENTS_ENABLED",
    "DOCUMENT_REQUIREMENT_UNAVAILABLE",
    "ENGINE_VERSION",
    "UNTRUSTED_PROMPT_HEADER",
    "AccessFamily",
    "AnalysisLimits",
    "ArchiveEntry",
    "ArchiveLimits",
    "ArchiveReading",
    "CandidateContext",
    "CoverageStatus",
    "Decision",
    "DeterministicExtractor",
    "DiscoveryResult",
    "DocumentAccessStatus",
    "DocumentAnalysis",
    "DocumentFetcher",
    "DocumentIntelligenceResult",
    "DocumentKind",
    "DocumentReference",
    "ExecutionRequirement",
    "ExtractionResult",
    "FetchLimits",
    "FetchResult",
    "HeuristicClassifier",
    "LinkageOutcome",
    "LinkageStatus",
    "LlmUsage",
    "Modality",
    "RejectionReason",
    "RejectionTally",
    "RequirementActor",
    "RequirementCandidate",
    "RequirementClassifier",
    "RequirementExtractionModel",
    "RequirementPhase",
    "RequirementQuantity",
    "RequirementType",
    "SemanticClassification",
    "TenderDocument",
    "TextBlock",
    "access_family",
    "analyze_document",
    "analyze_dossier",
    "auth_required_document",
    "build_classification_prompt",
    "classify_requirement",
    "content_hash",
    "context_for",
    "coverage_for",
    "decide",
    "dedupe_requirements",
    "detect_language",
    "detect_modality",
    "document_kind",
    "document_requirement_status",
    "expand",
    "extract_quantity",
    "extract_text",
    "linkage_metrics",
    "parse_classification",
    "read_archive",
    "references_from_ted_notice",
    "relevance_rank",
    "requirement_from",
    "simap_dossier",
    "sniff_media_type",
    "validate_candidates",
]
