"""SIGNAL-100 — le banc d'essai commercial de bout en bout (SPEC-009).

Ce module n'améliore aucun moteur : il les orchestre. SPEC-006 reste désactivée,
SPEC-007 et SPEC-008 restent gelées. Ce qui est mesuré ici n'est plus « la règle
est-elle correcte ? » mais « un commercial B2B aurait-il une raison crédible
d'investiguer ce gagnant maintenant ? ».

Découpage : la logique pure vit ici, le réseau vit dans `signal100_run.py`. Les
tests de la suite normale n'appellent donc jamais Internet (SPEC-009 §58).

Portabilité (SPEC-009 §54) : aucun chemin absolu, aucun chemin Windows, aucune
dépendance à l'état d'une machine. La racine du dépôt et le dossier de travail
se configurent par variable d'environnement.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import re
from collections.abc import Iterable, Sequence
from typing import Any

# ─── Emplacements, configurables ────────────────────────────────────────────────

ENV_ROOT = "KIVOU_ROOT"
ENV_WORKDIR = "KIVOU_SIGNAL100_WORKDIR"

#: Corpus antérieurs portant les quatre niveaux d'identité (`source`/`notice`/
#: `event`/`award`). Toute donnée SPEC-009 doit en être disjointe (§9, §10).
PRIOR_CORPORA_FULL = (
    "tests/fixtures/contract100/awards.json",
    "tests/fixtures/needs/need_final_corpus.json",
    "tests/fixtures/matching/signal_match_final_corpus.json",
)

#: Corpus antérieurs ne portant qu'une clé de notice `système:notice_id:version`
#: (les échantillons DEV et held-out de SPEC-007).
PRIOR_CORPORA_NOTICE_KEYS = (
    "tests/fixtures/needs/need100_dev.json",
    "tests/fixtures/needs/need100_heldout_corpus.json",
)

IDENTITY_LEVELS = ("publication", "notice", "procedure", "award identity")


def repo_root() -> pathlib.Path:
    """Racine du dépôt : `$KIVOU_ROOT` sinon le parent de `src/`.

    Aucun chemin absolu n'est écrit en dur : le même code tourne sur la machine
    de développement puis sur un VPS sans être retouché (§54).
    """
    configured = os.environ.get(ENV_ROOT)
    if configured:
        return pathlib.Path(configured).expanduser().resolve()
    return pathlib.Path(__file__).resolve().parents[3]


def workdir() -> pathlib.Path:
    """Dossier de travail déterministe, créé à la demande (§55)."""
    configured = os.environ.get(ENV_WORKDIR)
    path = (
        pathlib.Path(configured).expanduser()
        if configured
        else repo_root() / "tests" / "fixtures" / "signal100"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


# ─── Identités et disjonction (§10) ─────────────────────────────────────────────


def _rows_of(payload: Any) -> list[dict]:
    """Les lignes d'un corpus, qu'il soit une liste nue ou un objet `rows`."""
    return payload if isinstance(payload, list) else payload["rows"]


def load_rows(path: pathlib.Path) -> list[dict]:
    return _rows_of(json.loads(path.read_text(encoding="utf-8")))


def award_identity(row: dict) -> tuple:
    """Identité d'un award-lot : notice source, version, award, lot.

    C'est l'unité du banc (§7) et la clé d'unicité de `signal_id` (§16) : deux
    lots d'une même notice sont deux événements commerciaux distincts, mais un
    même lot ne doit jamais être compté deux fois.
    """
    award = row["award"]
    event_ref = award["event_ref"]
    return (
        event_ref["source_system"],
        event_ref["source_notice_id"],
        event_ref.get("notice_version"),
        award.get("source_award_id"),
        (award.get("lot") or {}).get("identifier"),
    )


def identities(rows: Sequence[dict]) -> dict[str, set]:
    """Les quatre niveaux d'identité d'un corpus (§10).

    Publication (`source` + `notice`), notice source, procédure, award-lot. Un
    niveau vide signale une extraction cassée, jamais une disjonction : c'est le
    test qui doit le refuser, pas cette fonction qui doit le masquer.
    """
    publications: set[tuple] = set()
    notices: set[tuple] = set()
    procedures: set[tuple] = set()
    awards: set[tuple] = set()
    for row in rows:
        provenance = row["event"]["provenance"]
        system = provenance["source_system"]
        publications.add((row["source"], row["notice"]))
        notices.add((system, provenance["source_notice_id"]))
        if provenance.get("source_procedure_id") is not None:
            procedures.add((system, provenance["source_procedure_id"]))
        awards.add(award_identity(row))
    return {
        "publication": publications,
        "notice": notices,
        "procedure": procedures,
        "award identity": awards,
    }


def _notice_key_identities(rows: Sequence[dict]) -> set[tuple]:
    """`système:notice_id:version` → identité de notice `(système, notice_id)`."""
    found: set[tuple] = set()
    for row in rows:
        key = row.get("key")
        if not key:
            continue
        system, _, rest = key.partition(":")
        notice_id, _, _version = rest.partition(":")
        if system and notice_id:
            found.add((system, notice_id))
    return found


def prior_identities(root: pathlib.Path | None = None) -> dict[str, set]:
    """L'union des identités déjà consommées par SPEC-007 et SPEC-008.

    Les corpus complets alimentent les quatre niveaux ; les corpus DEV/held-out
    de SPEC-007, qui ne portent qu'une clé de notice, alimentent le niveau
    `notice`. Une donnée SPEC-009 fraîche ne doit toucher aucun de ces ensembles.
    """
    base = root or repo_root()
    merged: dict[str, set] = {level: set() for level in IDENTITY_LEVELS}
    for relative in PRIOR_CORPORA_FULL:
        path = base / relative
        if not path.exists():
            raise FileNotFoundError(f"corpus antérieur introuvable : {path}")
        for level, values in identities(load_rows(path)).items():
            merged[level] |= values
    for relative in PRIOR_CORPORA_NOTICE_KEYS:
        path = base / relative
        if not path.exists():
            raise FileNotFoundError(f"corpus antérieur introuvable : {path}")
        merged["notice"] |= _notice_key_identities(load_rows(path))
    return merged


def disjointness_report(rows: Sequence[dict], prior: dict[str, set]) -> dict[str, dict]:
    """Le rapport de disjonction, niveau par niveau, avec les tailles extraites.

    Publier la taille des ensembles est le garde-fou de §10 : une extraction
    cassée produit zéro intersection, elle ne doit pas se lire comme une preuve.
    """
    fresh = identities(rows)
    return {
        level: {
            "fresh_identities": len(fresh[level]),
            "prior_identities": len(prior[level]),
            "intersection": sorted(str(item) for item in (fresh[level] & prior[level])),
        }
        for level in IDENTITY_LEVELS
    }


# ─── Identité d'un signal (§16) ─────────────────────────────────────────────────


def signal_id(
    award_identity_tuple: tuple,
    icp_id: str,
    match_policy_version: str,
    score_policy_version: str,
) -> str:
    """Identité déterministe d'un signal — jamais d'UUID aléatoire (§16).

    `award_ref` au sens de la SPEC est ici l'identité d'award-**lot** et non
    l'`EventRef` du modèle : deux lots d'une même notice partagent leur EventRef,
    et les confondre violerait « maximum 1 signal par award-lot » (§8).
    """
    parts = [*(("" if p is None else str(p)) for p in award_identity_tuple)]
    parts += [icp_id, match_policy_version, score_policy_version]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ─── Sûreté du vocabulaire (§50) ────────────────────────────────────────────────

#: Formulations interdites : elles transforment une hypothèse en certitude
#: d'achat. La frontière de vérité de §4 est un invariant produit, pas un
#: détail de rédaction.
FORBIDDEN_WORDINGS = (
    "will buy",
    "will hire",
    "confirmed demand",
    "confirmed need",
    "certain opportunity",
    "va acheter",
    "va recruter",
    "besoin confirmé",
    "demande certaine",
    "opportunité certaine",
)

_FORBIDDEN_PATTERNS = tuple(
    (wording, re.compile(re.escape(wording), re.IGNORECASE)) for wording in FORBIDDEN_WORDINGS
)


def forbidden_wording_hits(text: str) -> tuple[str, ...]:
    """Les formulations de certitude présentes dans un texte (§50), FR et EN."""
    return tuple(wording for wording, pattern in _FORBIDDEN_PATTERNS if pattern.search(text))


#: Limitation obligatoire de chaque signal tant que SPEC-006 est désactivée (§51).
DOCUMENT_MODE_DISCLOSURE = (
    "Need inferred from public award information. No validated execution requirement was available."
)


# ─── Composition du pool et sélection (§13, §14) ────────────────────────────────


@dataclasses.dataclass(frozen=True)
class PoolEntry:
    """Un signal `show` candidat : l'award-lot, l'ICP retenu, le score."""

    signal_id: str
    source: str
    notice: str
    award_key: tuple
    icp_id: str
    normalized_score: int
    band: str
    confidence: str
    contract_type: str
    sector: str
    country: str | None
    matched_needs: tuple[str, ...]


def best_match_per_award_lot(entries: Iterable[PoolEntry]) -> list[PoolEntry]:
    """Un seul signal par award-lot : meilleur score, puis `icp_id` croissant (§8).

    Un même événement commercial correspondant à plusieurs ICPs ne devient pas
    plusieurs signaux : le feed montrerait deux fois la même adjudication.
    """
    best: dict[tuple, PoolEntry] = {}
    for entry in entries:
        current = best.get(entry.award_key)
        if current is None or (-entry.normalized_score, entry.icp_id) < (
            -current.normalized_score,
            current.icp_id,
        ):
            best[entry.award_key] = entry
    return sorted(best.values(), key=lambda e: (-e.normalized_score, e.signal_id))


def cap_award_lots_per_notice(entries: Sequence[PoolEntry], *, cap: int = 2) -> list[PoolEntry]:
    """Au plus `cap` award-lots par notice (§8), de façon déterministe.

    Le tri est (score décroissant, `signal_id`) : aucune notice à lots multiples
    ne peut inonder le banc, et le choix ne dépend pas de l'ordre d'acquisition.
    """
    kept: list[PoolEntry] = []
    seen: dict[tuple, int] = {}
    for entry in sorted(entries, key=lambda e: (-e.normalized_score, e.signal_id)):
        key = (entry.source, entry.notice)
        if seen.get(key, 0) >= cap:
            continue
        seen[key] = seen.get(key, 0) + 1
        kept.append(entry)
    return kept


def terciles(entries: Sequence[PoolEntry]) -> dict[str, list[PoolEntry]]:
    """Découpe le pool `show` en trois zones de score (§14).

    Le découpage se fait par rang sur (score décroissant, `signal_id`) et non par
    valeur de score : les scores sont très discrets, des bornes par valeur
    produiraient des zones vides.
    """
    ordered = sorted(entries, key=lambda e: (-e.normalized_score, e.signal_id))
    size = len(ordered)
    first = size // 3
    second = 2 * size // 3
    return {
        "top": ordered[:first],
        "middle": ordered[first:second],
        "bottom": ordered[second:],
    }
