"""SPEC-006R5 §25 — la disjonction du futur held-out final, à trois niveaux.

FR-DCE-FINAL doit être disjoint de DEV-FR-DCE, des anciens held-out et du
corpus FR-DCE-1 par :

    consultation ID  ·  document SHA-256  ·  hash de phrase

Un seul niveau ne suffit pas : deux consultations distinctes peuvent partager
un CCAP type mot pour mot — seule l'empreinte de phrase l'attrape.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

from signals.documents.heldout3_build import (
    known_consultations,
    known_document_hashes,
    known_sentence_hashes,
)
from signals.documents.language import normalize_for_match

FIXTURES = pathlib.Path("tests/fixtures/documents")


def _rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())["rows"]


class TestDocumentHashes:
    def test_both_fr_corpora_are_covered(self) -> None:
        known = known_document_hashes()
        for name in ("fr_dce_candidates.json", "fr_dce_candidates_ext.json"):
            for row in _rows(name):
                assert row["document_hash"] in known


class TestSentenceHashes:
    def test_every_dev_sentence_is_fingerprinted(self) -> None:
        known = known_sentence_hashes()
        for name in ("fr_dce_candidates.json", "fr_dce_candidates_ext.json"):
            for row in _rows(name):
                digest = hashlib.sha256(normalize_for_match(row["excerpt"]).encode()).hexdigest()
                assert digest in known

    def test_an_unseen_sentence_is_not_fingerprinted(self) -> None:
        digest = hashlib.sha256(
            normalize_for_match("Une phrase entièrement neuve jamais échantillonnée.").encode()
        ).hexdigest()
        assert digest not in known_sentence_hashes()


class TestConsultations:
    def test_every_dev_consultation_is_excluded_from_future_builds(self) -> None:
        known = known_consultations()
        for name in ("fr_dce_candidates.json", "fr_dce_candidates_ext.json"):
            sources = json.loads((FIXTURES / name).read_text())["sources"]
            for source in sources:
                assert source["consultation"] in known
