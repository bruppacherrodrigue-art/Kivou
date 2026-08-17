"""Figer le contexte d'un candidat pour qu'une mesure reste rejouable.

DEV-3 a été mesuré avec un corpus qui ne stockait que l'extrait. Deux
conséquences, l'une visible et l'autre non :

- le voisinage manquait, donc les modèles déclaraient « fragment » des phrases
  que l'annotateur, qui avait le document, avait lues entières ;
- `source_text` valait l'extrait, donc la validation de preuve — « le passage
  se retrouve-t-il dans la source ? » — était vraie par construction.

Un `CandidateSnapshot` porte le voisinage réel **et** les blocs sources, de sorte
que la preuve se vérifie contre le document et non contre une copie de la
question. Le snapshot est un instantané : il ne recalcule rien, il enregistre ce
que l'extraction a produit à un instant donné, avec le hash du document.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from signals.documents.classification import _looks_like_heading, _trim, normalize_for_match
from signals.documents.extract import TextBlock
from signals.documents.spans import LogicalTextSpan
from signals.documents.triage import detect_language

_HEADING_LOOKBACK = 12
"""Même profondeur que `context_for` : le snapshot enregistre le contexte que le
modèle recevra, pas un contexte plus généreux qui rendrait la mesure optimiste."""


@dataclass(frozen=True)
class CandidateSnapshot:
    """Un candidat et tout ce qu'il faut pour le rejouer — ou le contredire."""

    candidate_id: int
    award_reference: str
    document_hash: str
    document_name: str
    media_type: str | None
    source_locator: str
    heading: str | None
    previous_block: str | None
    current_block: str
    next_block: str | None
    logical_span: str
    source_block_locators: tuple[str, ...]
    excerpt: str
    language: str | None = None
    # Une phrase à cheval sur plusieurs blocs porte un extrait BRUT par bloc
    # traversé — (localisation, texte tel qu'il figure dans le bloc). Vide pour
    # un candidat mono-bloc : son évidence est l'extrait dans `current_block`.
    # SPEC-006R5 §7 : jamais une citation unique recomposée.
    evidence_pieces: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["source_block_locators"] = list(self.source_block_locators)
        data["evidence_pieces"] = [list(piece) for piece in self.evidence_pieces]
        return data

    def __post_init__(self) -> None:
        # `tuple` après désérialisation JSON, qui rend des listes.
        object.__setattr__(self, "source_block_locators", tuple(self.source_block_locators))
        object.__setattr__(
            self,
            "evidence_pieces",
            tuple((locator, text) for locator, text in self.evidence_pieces),
        )


@dataclass(frozen=True)
class EvidenceCheck:
    """Le verdict du validateur d'évidence — et la preuve brute qui le fonde."""

    ok: bool
    pieces: tuple[tuple[str, str], ...] = ()
    failure: str | None = None


def validate_excerpt(excerpt: str, snapshot: CandidateSnapshot) -> EvidenceCheck:
    """SPEC-006R5 §13 — la validation déterministe, absolue, d'un extrait cité.

    L'extrait doit se retrouver exactement (aux espaces près, comme partout) :

    - dans le bloc source du candidat — évidence mono-bloc ; ou
    - dans les morceaux BRUTS stockés d'une phrase à cheval sur plusieurs
      blocs — évidence multi-bloc, un extrait par bloc traversé (§7).

    Une correspondance qui n'existerait que dans la vue recollée, sans morceaux
    bruts pour la porter, n'est pas une preuve : `RAW_EXCERPT_FAILURE`. C'est
    ce validateur — pas le modèle — qui garantit qu'aucun extrait inventé
    n'atteint le produit (§14).
    """
    needle = normalize_for_match(excerpt)
    if not needle:
        return EvidenceCheck(False, failure="raw_excerpt_failure")

    if needle in normalize_for_match(snapshot.current_block):
        return EvidenceCheck(True, ((snapshot.source_locator, excerpt),))

    if snapshot.evidence_pieces:
        for locator, text in snapshot.evidence_pieces:
            if needle in normalize_for_match(text):
                return EvidenceCheck(True, ((locator, excerpt),))
        joined = normalize_for_match(" ".join(text for _, text in snapshot.evidence_pieces))
        if needle in joined:
            return EvidenceCheck(True, tuple(snapshot.evidence_pieces))

    return EvidenceCheck(False, failure="raw_excerpt_failure")


def excerpt_locates_in_blocks(excerpt: str, blocks: Sequence[TextBlock]) -> bool:
    """L'extrait se retrouve-t-il, aux espaces près, dans un bloc source ?

    On cherche bloc par bloc et non dans un texte concaténé : un extrait qui
    n'existerait qu'à cheval sur une frontière artificielle n'est pas une preuve.
    Les extraits réellement à cheval sont traités par `LogicalTextSpan.pieces_for`,
    qui rend un morceau brut par bloc traversé.
    """
    needle = normalize_for_match(excerpt)
    if not needle:
        return False
    return any(needle in normalize_for_match(block.text) for block in blocks)


def _heading_before(blocks: Sequence[TextBlock], index: int) -> str | None:
    for previous in range(index - 1, max(index - _HEADING_LOOKBACK, -1), -1):
        if _looks_like_heading(blocks[previous].text):
            return _trim(blocks[previous].text)
    return None


def _span_for(spans: Sequence[LogicalTextSpan], block: TextBlock) -> LogicalTextSpan | None:
    for span in spans:
        if any(candidate is block for candidate in span.blocks):
            return span
    return None


def guess_language(text: str) -> str | None:
    """La langue du bloc, déléguée au détecteur du tri — jamais réimplémentée.

    Le champ `language` de SPEC-006R4 §11 est explicitement « si connue », et
    `detect_language` répond `None` dès que l'écart avec la deuxième langue est
    trop faible. Une étiquette incertaine vaut mieux absente que fausse : elle
    servirait à expliquer un désaccord, et une mauvaise l'expliquerait de travers.
    """
    return detect_language(text)


def snapshot_candidate(
    *,
    candidate_id: int,
    award_reference: str,
    document_name: str,
    document_hash: str,
    media_type: str | None,
    blocks: Sequence[TextBlock],
    index: int,
    excerpt: str,
    spans: Sequence[LogicalTextSpan] = (),
) -> CandidateSnapshot:
    """Fige un candidat avec son voisinage réel.

    Refuse un extrait introuvable dans les blocs : un corpus d'évaluation ne doit
    pas pouvoir contenir une citation que le document ne porte pas. Une phrase à
    cheval sur plusieurs blocs (SPEC-006R5 §7) est acceptée si — et seulement
    si — son span la décompose en morceaux bruts, un par bloc traversé, dont la
    réunion redonne la phrase sans un caractère inventé.
    """
    block = blocks[index]
    span = _span_for(spans, block)

    pieces: tuple = ()
    if not excerpt_locates_in_blocks(excerpt, blocks):
        pieces = span.pieces_for(excerpt) if span is not None else ()
        if len(pieces) < 2:
            raise ValueError(f"extrait introuvable dans les blocs sources : {excerpt[:60]!r}")
        rebuilt = " ".join(piece.text for piece in pieces)
        if normalize_for_match(rebuilt) != normalize_for_match(excerpt):
            raise ValueError(
                f"extrait multi-bloc non reconstructible depuis le brut : {excerpt[:60]!r}"
            )

    return CandidateSnapshot(
        candidate_id=candidate_id,
        award_reference=award_reference,
        document_hash=document_hash,
        document_name=document_name,
        media_type=media_type,
        source_locator=block.locator,
        heading=_heading_before(blocks, index),
        previous_block=blocks[index - 1].text if index > 0 else None,
        current_block=block.text,
        next_block=blocks[index + 1].text if index + 1 < len(blocks) else None,
        logical_span=span.text if span is not None else block.text,
        source_block_locators=tuple(b.locator for b in (span.blocks if span else (block,))),
        excerpt=excerpt,
        language=guess_language(block.text),
        evidence_pieces=tuple((piece.block.locator, piece.text) for piece in pieces),
    )
