"""Le document et l'exigence comme objets — ce qu'ils refusent de représenter.

Deux invariants portent tout SPEC-006 :

- un document **récupéré** porte l'empreinte de ses octets, un document **non
  récupéré** n'en porte pas — sans quoi « j'ai lu ce fichier » deviendrait
  invérifiable ;
- une exigence sans extrait documentaire n'existe pas.

Le reste (versioning, distinction accès/absence) découle de ces deux règles.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from signals.documents import (
    ENGINE_VERSION,
    ExecutionRequirement,
    RequirementQuantity,
    TenderDocument,
    coverage_for,
)
from signals.domain import Evidence

RETRIEVED_AT = dt.datetime(2026, 8, 16, 15, 47, tzinfo=dt.UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "source_system": "ted",
        "source_kind": "tender_document",
        "source_procedure_id": "PT-2026-acingov",
        "source_url": "https://www.acingov.pt/acingovprod/2/zonaPublica/x",
        "path": "1_Caderno_encargos_AE.pdf — page 12",
        "excerpt": "O adjudicatário deve assegurar a manutenção do equipamento.",
        "retrieved_at": RETRIEVED_AT,
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def _requirement(**overrides: object) -> ExecutionRequirement:
    fields: dict[str, object] = {
        "requirement_type": "maintenance_obligation",
        "modality": "mandatory",
        "statement": "O adjudicatário deve assegurar a manutenção do equipamento.",
        "confidence": "high",
        "evidence": (_evidence(),),
        "extraction_method": "deterministic",
        "engine_version": ENGINE_VERSION,
    }
    fields.update(overrides)
    return ExecutionRequirement(**fields)  # type: ignore[arg-type]


class TestRetrievalInvariant:
    def test_a_retrieved_document_must_carry_its_hash(self) -> None:
        with pytest.raises(ValidationError, match="content_hash"):
            TenderDocument(source_system="ted", name="a.pdf", access_status="available")

    def test_a_document_never_retrieved_must_not_carry_a_hash(self) -> None:
        with pytest.raises(ValidationError, match="rien n'a été récupéré"):
            TenderDocument(
                source_system="simap",
                name="dossier",
                access_status="auth_required",
                content_hash=HASH_A,
            )

    def test_an_unsupported_format_was_still_retrieved_and_keeps_its_hash(self) -> None:
        document = TenderDocument(
            source_system="ted", name="plan.dwg", access_status="unsupported", content_hash=HASH_A
        )
        assert document.is_retrieved
        assert not document.is_readable

    def test_a_document_with_no_name_no_url_and_no_path_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="sans nom"):
            TenderDocument(source_system="ted", access_status="not_found")


class TestVersioning:
    def test_two_files_sharing_a_name_but_not_a_hash_stay_distinct(self) -> None:
        first = TenderDocument(
            source_system="ted", name="CCTP.pdf", access_status="available", content_hash=HASH_A
        )
        second = first.model_copy(update={"content_hash": HASH_B})
        assert first.identity() != second.identity()

    def test_the_same_bytes_under_two_paths_stay_distinct(self) -> None:
        base = TenderDocument(
            source_system="ted", name="CCTP.pdf", access_status="available", content_hash=HASH_A
        )
        in_archive = base.model_copy(update={"path_in_container": "lot1/CCTP.pdf"})
        assert base.identity() != in_archive.identity()

    def test_a_document_is_immutable(self) -> None:
        document = TenderDocument(
            source_system="ted", name="CCTP.pdf", access_status="available", content_hash=HASH_A
        )
        with pytest.raises(ValidationError):
            document.name = "autre.pdf"  # type: ignore[misc]


class TestAccessVocabulary:
    def test_locked_and_absent_are_two_different_answers(self) -> None:
        locked = TenderDocument(
            source_system="simap", name="dossier", access_status="auth_required"
        )
        assert coverage_for((locked,), 0) == "auth_required"
        assert coverage_for((), 0) == "no_documents"

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("download_failed", "download_failed"),
            ("not_found", "download_failed"),
            ("too_large", "download_failed"),
            ("unsupported", "unsupported_documents"),
            ("encrypted", "unsupported_documents"),
        ],
    )
    def test_a_technical_failure_never_becomes_an_absence(self, status: str, expected: str) -> None:
        """Une adresse publiée puis morte ne prouve pas que le marché est sans dossier.

        `no_documents` est réservé au cas où **rien n'a jamais été référencé**.
        """
        document = TenderDocument(
            source_system="ted",
            name="a.pdf",
            access_status=status,  # type: ignore[arg-type]
            content_hash=HASH_A if status in ("unsupported", "encrypted") else None,
        )
        assert coverage_for((document,), 0) == expected


class TestAccessFamilies:
    """SPEC-006R : garder les cinq familles d'accès séparées, sans les fondre.

    4,6 % de liens TED servent un fichier. Ce n'est pas un échec du moteur : les
    autres familles décrivent où se trouve réellement le dossier, et c'est ce qui
    permettra plus tard de choisir 3 à 5 portails à instrumenter.
    """

    @pytest.mark.parametrize(
        ("status", "family"),
        [
            ("available", "direct_document_access"),
            ("unsupported", "direct_document_access"),
            ("encrypted", "direct_document_access"),
            ("external", "external_portal"),
            ("auth_required", "auth_required"),
            ("not_found", "not_found"),
            ("download_failed", "download_failed"),
            ("too_large", "download_failed"),
        ],
    )
    def test_each_status_belongs_to_one_family(self, status: str, family: str) -> None:
        from signals.documents.model import access_family

        assert access_family(status) == family  # type: ignore[arg-type]

    def test_a_retrieved_but_unreadable_file_still_counts_as_direct_access(self) -> None:
        """Le fichier a bien été servi : c'est le format qui manque, pas l'accès."""
        from signals.documents.model import access_family

        assert access_family("unsupported") == "direct_document_access"

    def test_the_families_partition_the_status_vocabulary(self) -> None:
        from typing import get_args

        from signals.documents.model import DocumentAccessStatus, access_family

        assert {access_family(status) for status in get_args(DocumentAccessStatus)} == {
            "direct_document_access",
            "external_portal",
            "auth_required",
            "not_found",
            "download_failed",
        }


class TestRequirementInvariant:
    def test_a_requirement_without_evidence_is_impossible(self) -> None:
        with pytest.raises(ValidationError):
            _requirement(evidence=())

    def test_evidence_from_the_notice_does_not_prove_an_execution_requirement(self) -> None:
        with pytest.raises(ValidationError, match="document de marché"):
            _requirement(evidence=(_evidence(source_kind="publication_field", excerpt="x"),))

    def test_evidence_without_excerpt_proves_nothing(self) -> None:
        with pytest.raises(ValidationError, match="sans extrait"):
            _requirement(evidence=(_evidence(excerpt=None),))

    def test_an_informational_statement_is_not_a_requirement(self) -> None:
        with pytest.raises(ValidationError, match="informatif"):
            _requirement(modality="informational")

    def test_a_prohibition_is_a_requirement_but_not_an_obligation(self) -> None:
        requirement = _requirement(modality="prohibited")
        assert not requirement.is_obligation

    def test_a_quantity_keeps_what_the_document_wrote(self) -> None:
        requirement = _requirement(quantity=RequirementQuantity(raw="30 %", value=30.0, unit="%"))
        assert requirement.quantity is not None
        assert requirement.quantity.raw == "30 %"

    def test_a_requirement_is_immutable(self) -> None:
        requirement = _requirement()
        with pytest.raises(ValidationError):
            requirement.modality = "optional"  # type: ignore[misc]

    def test_the_engine_version_travels_with_the_requirement(self) -> None:
        assert _requirement().engine_version == ENGINE_VERSION
