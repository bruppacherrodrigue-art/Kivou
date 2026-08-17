"""Recoller ce que la mise en page a coupé — sans rien ajouter ni retirer.

SPEC-006R3 a chiffré le problème : sur huit exigences manquées par le modèle,
six étaient **correctement comprises** et refusées au seul motif que la phrase
était tronquée. Elle l'était par le PDF :

    page 6  « … Izvajalec mora naročniku javiti vsako okvaro na opremi, ki jo/jih »
    page 7  « Vzorec pogodbe 7  13. člen  je povzročil pri izvajanju del. »

Demander à un modèle de langue de deviner ce recollement, c'est lui faire porter
un travail que l'extracteur peut faire seul, et de façon vérifiable. Ce module
s'en charge en deux temps :

1. **retirer les lignes de service** — en-têtes et pieds de page répétés d'une
   page à l'autre, qui ne sont pas du texte contractuel et qui s'intercaleraient
   au milieu d'une phrase recollée ;
2. **assembler les blocs contigus** dont le premier ne se termine pas.

Trois garanties tenues par construction :

- les `TextBlock` bruts ne sont **jamais** modifiés ;
- chaque `LogicalTextSpan` garde la liste ordonnée de ses blocs sources ;
- une phrase à cheval sur deux blocs se retrouve en **deux extraits bruts**,
  chacun avec sa localisation d'origine — jamais une citation unique qui
  prétendrait venir d'un seul endroit.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass

from signals.documents.extract import TextBlock

# ─── Lignes de service ──────────────────────────────────────────────────────────

_EDGE_LINES = 2
"""Nombre de lignes examinées en tête et en pied de chaque page. Au-delà, une
répétition est plus vraisemblablement du contenu (une clause type reprise)."""

_MIN_PAGES = 3
"""Sur deux pages, une ligne commune peut être une coïncidence."""

_REPEAT_RATIO = 0.5
_DIGITS = re.compile(r"\d+")


def _skeleton(line: str) -> str:
    """La ligne sans ses nombres : « 5 | 91 UKC » et « 6 | 91 UKC » sont la même."""
    return _DIGITS.sub("#", re.sub(r"\s+", " ", line)).strip().casefold()


_SERVICE_MAX_CHARS = 80


def _looks_like_service_line(line: str) -> bool:
    """Un en-tête est court et n'est pas une phrase.

    Sans cette précaution, une ligne de contenu répétée à quelques chiffres près
    (« Contenu 3. », « Contenu 4. ») serait prise pour un pied de page.
    """
    stripped = line.strip()
    return (
        bool(stripped)
        and len(stripped) <= _SERVICE_MAX_CHARS
        and not stripped.endswith((".", "!", "?", ";"))
    )


def strip_running_headers(pages: list[str] | tuple[str, ...]) -> list[str]:
    """Retire les lignes qui se répètent en tête ou en pied de page.

    Le numéro de page change à chaque fois : la comparaison se fait donc sur la
    ligne débarrassée de ses chiffres. Une ligne isolée n'est jamais retirée —
    en cas de doute, le texte reste.
    """
    pages = list(pages)
    if len(pages) < _MIN_PAGES:
        return pages

    counts: collections.Counter[str] = collections.Counter()
    for page in pages:
        lines = [line for line in page.split("\n") if line.strip()]
        edges = lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]
        counts.update({_skeleton(line) for line in edges if _looks_like_service_line(line)})

    threshold = max(_MIN_PAGES, int(len(pages) * _REPEAT_RATIO))
    recurring = {key for key, count in counts.items() if count >= threshold and key}

    cleaned: list[str] = []
    for page in pages:
        lines = page.split("\n")
        keep = [
            line
            for position, line in enumerate(lines)
            if not (
                (position < _EDGE_LINES or position >= len(lines) - _EDGE_LINES)
                and _looks_like_service_line(line)
                and _skeleton(line) in recurring
            )
        ]
        cleaned.append("\n".join(keep).strip())
    return cleaned


# ─── Assemblage ─────────────────────────────────────────────────────────────────

_TERMINATED = (".", "!", "?", ":", ";", "…", '"', "»", ")")
_NEW_ITEM = re.compile(r"^\s*([a-z]\)|\d+[\.\)]|[-–•*]|[IVXLC]+\.)\s")
_HEADING_MAX_CHARS = 120
_HEADING_NUMBER = re.compile(r"^\s*(\d+[\.\)]|[IVXLC]+\.|[A-Z]\)|§)\s*\S")
JOINER = " "


def _looks_like_heading(text: str) -> bool:
    """Un titre est numéroté ou en capitales — jamais un simple début de phrase.

    La version large de `triage` (« court et sans point final ») ne convient pas
    ici : elle prenait « Izvajalec mora naročniku javiti vsako okvaro, ki jo/jih »
    pour un titre, et empêchait précisément le recollement recherché.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > _HEADING_MAX_CHARS:
        return False
    if _HEADING_NUMBER.match(stripped):
        return True
    letters = [char for char in stripped if char.isalpha()]
    return bool(letters) and sum(char.isupper() for char in letters) / len(letters) >= 0.6


def _find_tolerating_spaces(haystack: str, needle: str) -> tuple[int, int] | None:
    """Position d'un extrait dans un texte, aux espaces près — ou rien."""
    start = haystack.find(needle)
    if start != -1:
        return start, start + len(needle)
    tokens = needle.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(pattern, haystack)
    if match is None:
        return None
    return match.start(), match.end()


@dataclass(frozen=True)
class SpanPiece:
    """La part d'une phrase portée par un bloc source, telle qu'elle y figure."""

    block: TextBlock
    text: str


@dataclass(frozen=True)
class BlockRange:
    """Où un bloc source se trouve dans le texte assemblé, et de combien il est décalé.

    `offset` est la position, DANS le bloc brut, du premier caractère repris :
    non nulle quand un en-tête de page a été retiré de la vue assemblée. C'est
    ce décalage qui permet de rendre un extrait **brut** du bloc, et pas une
    recomposition.
    """

    start: int
    end: int
    offset: int


@dataclass(frozen=True)
class LogicalTextSpan:
    """Une unité de texte lisible, et la trace exacte de ses blocs d'origine."""

    text: str
    blocks: tuple[TextBlock, ...]
    ranges: tuple[BlockRange, ...]

    @property
    def locator(self) -> str:
        if len(self.blocks) == 1:
            return self.blocks[0].locator
        return f"{self.blocks[0].locator} → {self.blocks[-1].locator}"

    @property
    def method(self) -> str:
        return self.blocks[0].method

    @property
    def page(self) -> int | None:
        return self.blocks[0].page

    def pieces_for(self, excerpt: str) -> tuple[SpanPiece, ...]:
        """Découpe un extrait en morceaux, un par bloc source traversé.

        C'est ce qui permet à une exigence à cheval sur deux pages de porter
        **deux** preuves, chacune citant son bloc — au lieu d'une citation
        recomposée qui n'existerait nulle part dans le document.

        La recherche tolère les seules différences d'espaces — la même
        tolérance que `normalize_for_match`, pas une de plus : la vue préserve
        la longueur des séparateurs recollés, un extrait cité avec des espaces
        réduits doit quand même retrouver son passage.
        """
        located = _find_tolerating_spaces(self.text, excerpt)
        if located is None:
            return ()
        start, end = located

        pieces: list[SpanPiece] = []
        for block, span_range in zip(self.blocks, self.ranges, strict=True):
            overlap_start = max(start, span_range.start)
            overlap_end = min(end, span_range.end)
            if overlap_start >= overlap_end:
                continue
            # Retour dans le bloc BRUT : l'extrait cité vient du document, pas
            # de la vue assemblée.
            raw_start = span_range.offset + (overlap_start - span_range.start)
            raw_end = span_range.offset + (overlap_end - span_range.start)
            fragment = block.text[raw_start:raw_end].strip()
            if fragment:
                pieces.append(SpanPiece(block=block, text=fragment))
        return tuple(pieces)


def _continues_views(
    previous: TextBlock, following: TextBlock, previous_text: str, following_text: str
) -> bool:
    """Même règle que `_continues`, appliquée aux vues débarrassées des en-têtes."""
    return _continues(
        TextBlock(locator=previous.locator, text=previous_text, method=previous.method),
        TextBlock(locator=following.locator, text=following_text, method=following.method),
    )


def _continues(previous: TextBlock, following: TextBlock) -> bool:
    """Deux blocs appartiennent-ils manifestement à la même unité de texte ?

    Volontairement restrictif : même méthode d'extraction, blocs contigus, le
    premier ne se termine pas, le second n'ouvre pas une nouvelle énumération, et
    aucun des deux n'est un titre. Une ressemblance sémantique ne suffit jamais.
    """
    if previous.method != following.method:
        return False
    # Une cellule de tableau est une unité en soi : sa voisine est une autre valeur.
    if previous.method == "xlsx_cell":
        return False
    if _looks_like_heading(previous.text) or _looks_like_heading(following.text):
        return False
    if previous.text.rstrip().endswith(_TERMINATED):
        return False
    if _NEW_ITEM.match(following.text):
        return False
    if not (previous.text.strip() and following.text.strip()):
        return False
    # Une reprise en minuscule est le signe le plus sûr d'une phrase coupée.
    head = following.text.lstrip()[:1]
    return head.islower()


def _recurring_service_lines(blocks: list[TextBlock] | tuple[TextBlock, ...]) -> set[str]:
    """Les lignes de service répétées d'un bloc à l'autre, dans un même document."""
    if len(blocks) < _MIN_PAGES:
        return set()
    counts: collections.Counter[str] = collections.Counter()
    for block in blocks:
        lines = [line for line in block.text.split("\n") if line.strip()]
        edges = lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]
        counts.update({_skeleton(line) for line in edges if _looks_like_service_line(line)})
    threshold = max(_MIN_PAGES, int(len(blocks) * _REPEAT_RATIO))
    return {key for key, count in counts.items() if count >= threshold and key}


_SOFT_WRAP = re.compile(r"(?<=[^\s.!?:;»\)])[ \t]*\n[ \t]*(?=[a-zà-öø-ÿ0-9(])")


def _soften_wraps(text: str) -> str:
    """Recolle les lignes d'un même paragraphe, **sans changer la longueur**.

    C'est la coupure la plus fréquente et la plus coûteuse : un PDF impose un
    retour à la ligne au milieu d'une phrase, le découpeur en fait deux énoncés,
    et le second est un fragment. Le retour à la ligne est remplacé par une
    espace — un caractère pour un caractère — de sorte que toutes les positions
    restent valables et qu'un extrait puisse encore être retrouvé, brut, dans le
    bloc d'origine.

    Une ligne qui se termine par une ponctuation forte, ou dont la suivante
    commence par une majuscule ou une puce, n'est jamais recollée.

    Le séparateur peut contenir des espaces autour du retour à la ligne
    (« et ␣\\n européennes ») : il est remplacé par AUTANT d'espaces que de
    caractères consommés, sans quoi chaque recollement décalerait le mapping
    vue → brut et `pieces_for` citerait le mauvais passage — mesuré à 14
    caractères de dérive sur une page réelle de FR-DCE-1 (SPEC-006R5 §7).
    """
    return _SOFT_WRAP.sub(lambda match: " " * len(match.group(0)), text)


def _trim_view(text: str, offset: int) -> tuple[str, int]:
    """Ébarbe les blancs de bordure d'une vue, en gardant la trace du décalage.

    SPEC-006R5 §5 a montré le coût de ces blancs : après retrait d'un en-tête,
    la vue du bloc suivant commençait par « ␣\\n » — et le découpeur en phrases,
    qui coupe sur `\\n+`, recassait au raccord la phrase que le recollement
    venait de réparer. Un blanc ne porte aucune preuve : l'écarter ne retire
    rien du document, et l'offset avancé garde chaque extrait traçable au brut.
    """
    lead = len(text) - len(text.lstrip())
    return text.strip(), offset + lead


def _view(block: TextBlock, recurring: set[str]) -> tuple[str, int]:
    """La vue lisible d'un bloc : son texte sans les lignes de service de bordure.

    Retourne aussi le décalage du premier caractère conservé, pour que tout
    extrait puisse être ramené au texte brut du bloc.
    """
    if not recurring:
        return _trim_view(_soften_wraps(block.text), 0)
    lines = block.text.split("\n")
    start = 0
    while start < len(lines) and start < _EDGE_LINES:
        line = lines[start]
        if line.strip() and _looks_like_service_line(line) and _skeleton(line) in recurring:
            start += 1
            continue
        break
    end = len(lines)
    while end > start and end > len(lines) - _EDGE_LINES:
        line = lines[end - 1]
        if line.strip() and _looks_like_service_line(line) and _skeleton(line) in recurring:
            end -= 1
            continue
        break
    if start == 0 and end == len(lines):
        return _trim_view(_soften_wraps(block.text), 0)
    offset = sum(len(lines[i]) + 1 for i in range(start))
    return _trim_view(_soften_wraps("\n".join(lines[start:end])), offset)


def logical_spans(
    blocks: list[TextBlock] | tuple[TextBlock, ...], *, strip_headers: bool = True
) -> tuple[LogicalTextSpan, ...]:
    """Regroupe des blocs contigus en unités de texte lisibles.

    Aucun bloc n'est perdu : chacun appartient à exactement un span, et son texte
    brut reste intact — seule la **vue** assemblée écarte les en-têtes répétés.
    """
    recurring = _recurring_service_lines(blocks) if strip_headers else set()
    views = {id(block): _view(block, recurring) for block in blocks}

    spans: list[LogicalTextSpan] = []
    group: list[TextBlock] = []

    def flush() -> None:
        if not group:
            return
        parts: list[str] = []
        ranges: list[BlockRange] = []
        cursor = 0
        for position, block in enumerate(group):
            text, offset = views[id(block)]
            if position:
                cursor += len(JOINER)
                parts.append(JOINER)
            ranges.append(BlockRange(start=cursor, end=cursor + len(text), offset=offset))
            parts.append(text)
            cursor += len(text)
        spans.append(
            LogicalTextSpan(text="".join(parts), blocks=tuple(group), ranges=tuple(ranges))
        )
        group.clear()

    for block in blocks:
        previous = group[-1] if group else None
        if previous is not None and not _continues_views(
            previous, block, views[id(previous)][0], views[id(block)][0]
        ):
            flush()
        group.append(block)
    flush()
    return tuple(spans)
