"""Quoi lire d'abord, et dans quelle langue c'est écrit.

Un dossier réel n'est pas homogène. Celui de Postojna pèse 15 Mo dont 13 Mo de
plans d'architecte : le cahier des charges y tient dans un seul fichier de
368 Ko. Lire dans l'ordre du ZIP revient à dépenser l'essentiel du budget de
lecture sur des documents qui ne portent aucune obligation contractuelle.

Le tri se fait sur le **nom et le format**, jamais sur le contenu supposé : un
fichier dont le nom ne dit rien reste `unknown` plutôt que d'être deviné.
"""

from __future__ import annotations

import re
import unicodedata

from signals.documents.model import DocumentKind, TenderDocument

_ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".tar", ".gz", ".tgz")

# Ordre = priorité de reconnaissance. Le premier motif qui accroche décide.
_KIND_PATTERNS: tuple[tuple[DocumentKind, re.Pattern[str]], ...] = (
    ("form", re.compile(r"\b(espd|dume|obrazec|formulaire|formulario|declaracao modelo)\b")),
    ("notice_copy", re.compile(r"\b(anuncio|announcement|obvestilo|avis de march|bekanntmachung)")),
    (
        "bill_of_quantities",
        re.compile(
            r"\b(popis|predracun\w*|bordereau|bpu|metrado|quantit|prix unitaires|"
            r"precos unitarios|leistungsverzeichnis)"
        ),
    ),
    (
        "technical_specification",
        re.compile(
            r"(caderno (de )?encargos|cahier des charges|cctp|"
            r"dokumentacija v zvezi z oddajo|tehnicne specifikacije|"
            r"leistungsbeschreibung|lastenheft|specifica|specification|especificac)"
        ),
    ),
    (
        "procedure_rules",
        re.compile(
            r"(procedimento|reglement|regolamento|consultation|navodila ponudnikom|"
            r"vergabeunterlagen|instrucoes)"
        ),
    ),
    (
        "contract_conditions",
        re.compile(
            # Le slovène décline : `pogodba` seul ratait `pogodbe`, `pogodbo`,
            # `pogodbi` — donc `osnutek pogodbe` et `vzorec krovne pogodbe`,
            # qui sont exactement les pièces les plus denses en obligations.
            r"(conditions generales|clausulas contratuais|minuta do contrato|ccap|"
            r"vertragsbedingungen|pogodb\w*|contract conditions)"
        ),
    ),
    ("annex", re.compile(r"\b(anexo|annexe|annex|priloga|anlage)\b")),
)


def _fold(text: str) -> str:
    """Minuscules sans accent : « Minuta do anúncio » et « MINUTA DO ANUNCIO » sont un."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[_\-]+", " ", stripped).casefold()


def document_kind(name: str | None, *, media_type: str | None = None) -> DocumentKind:
    """La nature du document, d'après son nom et son format — jamais devinée."""
    lowered = (name or "").lower()
    if lowered.endswith(_ARCHIVE_SUFFIXES) or (media_type or "").endswith("zip"):
        return "archive"

    folded = _fold(name or "")
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(folded):
            return kind
    return "unknown"


# Un cahier des charges porte les obligations ; une copie d'annonce répète ce que
# l'avis disait déjà. L'ordre reflète ce rendement, pas une hiérarchie formelle.
_KIND_PRIORITY: dict[DocumentKind, int] = {
    "technical_specification": 0,
    "bill_of_quantities": 1,
    "contract_conditions": 2,
    "procedure_rules": 3,
    "annex": 4,
    "unknown": 5,
    "archive": 6,
    "form": 7,
    "notice_copy": 8,
}

UNREADABLE_RANK = 100


def relevance_rank(document: TenderDocument) -> int:
    """Rang de lecture : plus petit = lu en premier.

    Un document non lisible passe après tous les autres — il n'est pas écarté du
    dossier, il n'a simplement rien à offrir au moteur d'exigences.
    """
    if not document.is_readable:
        return UNREADABLE_RANK
    kind = document.kind
    if kind == "unknown":
        kind = document_kind(document.name, media_type=document.media_type)
    return _KIND_PRIORITY[kind]


# ─── Langue ─────────────────────────────────────────────────────────────────────

# Mots fonctionnels : ils suffisent à étiqueter une langue et ne prétendent à rien
# de plus. Kivou ne traduit pas — un extrait reste dans sa langue d'origine.
_FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "fr": frozenset(
        (
            "le",
            "la",
            "les",
            "des",
            "du",
            "doit",
            "doivent",
            "qui",
            "sont",
            "dans",
            "pour",
            "avec",
            "aux",
            "ainsi",
            "cette",
            "chaque",
            "lors",
            "selon",
            "toute",
            "ne",
            "pas",
            "à",
        )
    ),
    "pt": frozenset(
        (
            "o",
            "os",
            "as",
            "do",
            "dos",
            "da",
            "das",
            "deve",
            "devem",
            "sera",
            "serao",
            "sao",
            "no",
            "na",
            "nos",
            "nas",
            "com",
            "pelo",
            "pela",
            "ao",
            "aos",
            "ou",
        )
    ),
    "it": frozenset(
        (
            "il",
            "lo",
            "gli",
            "dei",
            "della",
            "delle",
            "deve",
            "devono",
            "che",
            "dal",
            "dalla",
            "nel",
            "nella",
            "con",
            "per",
            "alla",
            "ai",
            "anche",
            "entro",
        )
    ),
    "en": frozenset(
        (
            "the",
            "shall",
            "must",
            "of",
            "and",
            "to",
            "is",
            "are",
            "that",
            "by",
            "with",
            "for",
            "this",
            "each",
            "any",
            "in",
            "from",
        )
    ),
    "de": frozenset(
        (
            "der",
            "die",
            "das",
            "des",
            "dem",
            "den",
            "muss",
            "mussen",
            "ist",
            "sind",
            "mit",
            "fur",
            "nicht",
            "auch",
            "sowie",
            "bei",
            "im",
            "zu",
            "werden",
        )
    ),
    "sl": frozenset(
        (
            "mora",
            "morajo",
            "ki",
            "je",
            "so",
            "za",
            "pri",
            "ter",
            "se",
            "po",
            "ali",
            "kot",
            "mora",
            "biti",
            "pod",
        )
    ),
}

_MIN_TOKENS = 5
_MIN_MATCHES = 3
# Écart minimal avec la deuxième langue. Une avance d'une voix n'est pas une
# détection : sur le corpus réel, deux pièces slovènes se retrouvaient étiquetées
# « pt » et « en » pour un mot court partagé. Mieux vaut « inconnue ».
_MIN_MARGIN = 2
_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_language(text: str) -> str | None:
    """La langue du texte, ou rien.

    « Rien » est une réponse fréquente et légitime : un bordereau de quantités
    est fait de nombres, et lui coller une langue serait inventer un fait.
    """
    tokens = [_fold(token) for token in _TOKEN.findall(text)]
    if len(tokens) < _MIN_TOKENS:
        return None

    scores = {
        language: sum(token in words for token in tokens)
        for language, words in _FUNCTION_WORDS.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1]
    if best_score < _MIN_MATCHES or best_score - runner_up < _MIN_MARGIN:
        return None
    return best
