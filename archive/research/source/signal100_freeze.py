"""Le gel SIGNAL-100 (SPEC-009 §32) — empreintes avant toute lecture des résultats.

L'ordre compte et il est le cœur de l'honnêteté du banc :

1. les cent signaux sont choisis ;
2. les adjudications sont terminées ;
3. **puis** les empreintes sont calculées et le banc devient immuable ;
4. **seulement ensuite** les verdicts commerciaux sont comparés aux scores Kivou.

Inverser 3 et 4 permettrait d'ajuster le gold en regardant les métriques. Ce
module ne sait donc rien faire d'autre que compter des octets.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from signals.matching import (
    MATCH_POLICY_VERSION,
    REFERENCE_ICP_LIBRARY_VERSION,
    SCORE_POLICY_VERSION,
)
from signals.needs import ENGINE_VERSION as NEED_ENGINE_VERSION
from signals.understanding import ENGINE_VERSION as UNDERSTANDING_ENGINE_VERSION

COMMERCIAL_RUBRIC_VERSION = "commercial-signal-rubric-v1"

REFERENCE_ICPS_PATH = pathlib.Path("tests/fixtures/matching/reference_icps.json")


def sha256_of(path: pathlib.Path) -> str:
    """L'empreinte des octets sur disque, pas d'une re-sérialisation."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def engine_version_set() -> dict[str, str]:
    """Le jeu de versions sous lequel le banc a été produit (§32, §62)."""
    return {
        "understanding_engine": UNDERSTANDING_ENGINE_VERSION,
        "need_engine": NEED_ENGINE_VERSION,
        "match_policy": MATCH_POLICY_VERSION,
        "score_policy": SCORE_POLICY_VERSION,
        "reference_icp_library": REFERENCE_ICP_LIBRARY_VERSION,
    }


def freeze(corpus_path: pathlib.Path, gold_path: pathlib.Path) -> dict[str, Any]:
    """Calcule le sceau du banc. À n'appeler qu'une fois l'adjudication close."""
    return {
        "frozen": True,
        "signal100_corpus_sha256": sha256_of(corpus_path),
        "signal100_gold_sha256": sha256_of(gold_path),
        "commercial_rubric_version": COMMERCIAL_RUBRIC_VERSION,
        "engine_version_set": engine_version_set(),
        "icp_library_sha256": sha256_of(REFERENCE_ICPS_PATH),
    }


def write_seal(
    corpus_path: pathlib.Path, gold_path: pathlib.Path, seal_path: pathlib.Path
) -> dict[str, Any]:
    seal = freeze(corpus_path, gold_path)
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=1), encoding="utf-8")
    return seal
