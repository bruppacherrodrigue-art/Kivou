"""Normalisations déterministes pour le RAPPROCHEMENT — jamais pour l'affichage.

Toutes les fonctions de ce module produisent des formes de comparaison. Aucune
ne remplace la valeur publiée : `legal_name` et `identifiers` gardent partout
l'écriture de la source.

**Ce que la normalisation ne prouve pas.** Deux noms qui se normalisent
identiquement sont des candidats, pas la même entreprise. Retirer une forme
juridique n'est jamais à soi seul une preuve d'identité : `Alpha SA` et
`Alpha Holding SA` se distinguent par un mot, pas par leur forme juridique.
"""

from __future__ import annotations

import re
import unicodedata

# Formes juridiques reconnues, par pays de rencontre. Elles sont retirées pour
# obtenir un noyau comparable — jamais pour conclure.
LEGAL_FORMS = (
    # Suisse / France / Belgique / Luxembourg
    "sa",
    "s.a.",
    "ag",
    "sàrl",
    "sarl",
    "s.à.r.l.",
    "gmbh",
    "sagl",
    "sagl.",
    "société anonyme",
    "aktiengesellschaft",
    "s.a.r.l",
    "sprl",
    "scrl",
    # Allemagne / Autriche
    "gmbh & co. kg",
    "kg",
    "ohg",
    "eg",
    "e.g.",
    "mbh",
    "se",
    # Italie / Espagne / Portugal
    "srl",
    "s.r.l.",
    "spa",
    "s.p.a.",
    "sl",
    "s.l.",
    "slu",
    "sau",
    "lda",
    "s.a",
    # Pays-Bas / Scandinavie
    "bv",
    "b.v.",
    "nv",
    "n.v.",
    "as",
    "a/s",
    "ab",
    "oy",
    "aps",
    "asa",
    # Europe centrale et orientale
    "s.r.o.",
    "sro",
    "spol. s r.o.",
    "sp. z o.o.",
    "sp. z o. o.",
    "zoo",
    "d.o.o.",
    "d. o. o.",
    "s. r. o.",
    "kft",
    "zrt",
    "nyrt",
    "sa.",
    "s.c.",
    # Anglo
    "ltd",
    "ltd.",
    "limited",
    "plc",
    "llc",
    "inc",
    "inc.",
)

_WHITESPACE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """`Müller` → `Muller`, `Zürich` → `Zurich`. Décomposition Unicode, rien de plus.

    Suffisant pour rapprocher, insuffisant pour conclure : `Müller` et `Mueller`
    ne se rejoignent pas ici, et c'est voulu — ce sont deux graphies dont
    l'équivalence dépend de l'entreprise, pas d'une règle.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _letters_and_digits(text: str) -> str:
    """Garde lettres et chiffres de TOUTE écriture, remplace le reste par un espace.

    Filtrer sur `[a-z0-9]` serait une faille : `Б. БРАУН МЕДИКАЛ ЕООД` et
    `СИНЕРГОН ЕНЕРДЖИ ООД` — deux entreprises bulgares distinctes du corpus —
    se réduiraient toutes deux à la chaîne vide, et se rapprocheraient donc
    l'une de l'autre. Le cyrillique, le grec et le reste traversent intacts.
    """
    return "".join(char if unicodedata.category(char)[0] in "LN" else " " for char in text)


def _join_initials(tokens: list[str]) -> list[str]:
    """Recolle les suites de lettres isolées : `s a` → `sa`, `d o o` → `doo`.

    La ponctuation d'une forme juridique ne doit pas la faire éclater : sans
    cela `ACME S.A.` donnerait `acme s a` et `Acme SA` donnerait `acme sa`, deux
    formes qui ne se rejoindraient jamais alors qu'elles désignent la même
    écriture.
    """
    joined: list[str] = []
    run: list[str] = []
    for token in tokens:
        if len(token) == 1:
            run.append(token)
            continue
        if run:
            joined.append("".join(run))
            run = []
        joined.append(token)
    if run:
        joined.append("".join(run))
    return joined


def matching_name(name: str) -> str:
    """Forme de comparaison d'une raison sociale, forme juridique CONSERVÉE.

    C'est la forme par défaut : elle absorbe casse, accents, ponctuation et
    espaces, mais garde tous les mots, dans toutes les écritures. `ACME S.A.` et
    `Acme SA` s'y rejoignent ; `Alpha SA` et `Alpha Holding SA` non.
    """
    text = _letters_and_digits(strip_accents(name).casefold())
    return " ".join(_join_initials(_WHITESPACE.sub(" ", text).strip().split()))


def name_core(name: str) -> str:
    """Le noyau du nom, forme juridique retirée — pour SUGGÉRER, pas pour fusionner.

    `Müller Bau AG` → `muller bau`. Les formes en plusieurs mots comptent :
    `MES d.o.o.` se normalise en `mes d o o`, et sans les retirer comme SÉQUENCE,
    `MES d.o.o.` et `ROCHE d.o.o.` partageraient les jetons `d` et `o` — une
    ressemblance entièrement fabriquée par la forme juridique slovène.

    Utilisé uniquement à la génération de candidats : deux noyaux identiques
    peuvent parfaitement désigner deux entités distinctes.
    """
    tokens = matching_name(name).split()
    forms = sorted(
        (tuple(matching_name(form).split()) for form in LEGAL_FORMS),
        key=len,
        reverse=True,
    )

    def strip(tokens: list[str]) -> tuple[list[str], bool]:
        for form in forms:
            size = len(form)
            if size and len(tokens) > size and tuple(tokens[-size:]) == form:
                return tokens[:-size], True
            if size and len(tokens) > size and tuple(tokens[:size]) == form:
                return tokens[size:], True
        return tokens, False

    changed = True
    while changed:
        tokens, changed = strip(tokens)
    return " ".join(tokens)


def matching_address(address: str | None) -> str | None:
    """Forme de comparaison d'une adresse. Aucun géocodage, aucune complétion."""
    if not address:
        return None
    text = _letters_and_digits(strip_accents(address).casefold())
    return _WHITESPACE.sub(" ", text).strip() or None


_POSTAL = re.compile(r"\b(\d{4,6})\b")


def postal_code(address: str | None) -> str | None:
    """Extrait un code postal plausible d'une adresse libre.

    Preuve d'appoint seulement : deux entreprises peuvent partager un code
    postal, et une adresse peut n'en contenir aucun.
    """
    if not address:
        return None
    found = _POSTAL.search(address)
    return found.group(1) if found else None


def name_similarity(left: str, right: str) -> float:
    """Similarité de tokens entre deux noyaux de noms, dans [0, 1].

    Jaccard sur les mots : déterministe, sans dépendance, sans seuil implicite.
    Sert exclusivement au classement de candidats — **jamais** à décider une
    fusion (voir `resolver`, palier 5).
    """
    left_tokens = set(name_core(left).split())
    right_tokens = set(name_core(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
